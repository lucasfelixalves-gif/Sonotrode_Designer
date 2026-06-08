from __future__ import annotations

import random
from enum import IntEnum

from PySide6.QtCore import QBasicTimer, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame


class Tetromino(IntEnum):
    NoShape = 0
    ZShape = 1
    SShape = 2
    LineShape = 3
    TShape = 4
    SquareShape = 5
    LShape = 6
    MirroredLShape = 7


class Shape:
    coords_table = (
        ((0, 0), (0, 0), (0, 0), (0, 0)),
        ((0, -1), (0, 0), (-1, 0), (-1, 1)),
        ((0, -1), (0, 0), (1, 0), (1, 1)),
        ((0, -1), (0, 0), (0, 1), (0, 2)),
        ((-1, 0), (0, 0), (1, 0), (0, 1)),
        ((0, 0), (1, 0), (0, 1), (1, 1)),
        ((-1, -1), (0, -1), (0, 0), (0, 1)),
        ((1, -1), (0, -1), (0, 0), (0, 1)),
    )

    def __init__(self) -> None:
        self.coords = [[0, 0] for _ in range(4)]
        self._piece_shape = Tetromino.NoShape
        self.set_shape(Tetromino.NoShape)

    def shape(self) -> Tetromino:
        return self._piece_shape

    def set_shape(self, shape: Tetromino) -> None:
        table = Shape.coords_table[int(shape)]
        for i in range(4):
            for j in range(2):
                self.coords[i][j] = table[i][j]
        self._piece_shape = shape

    def set_random_shape(self) -> None:
        self.set_shape(Tetromino(random.randint(1, 7)))

    def x(self, index: int) -> int:
        return self.coords[index][0]

    def y(self, index: int) -> int:
        return self.coords[index][1]

    def set_x(self, index: int, value: int) -> None:
        self.coords[index][0] = value

    def set_y(self, index: int, value: int) -> None:
        self.coords[index][1] = value

    def min_x(self) -> int:
        return min(self.coords[i][0] for i in range(4))

    def max_x(self) -> int:
        return max(self.coords[i][0] for i in range(4))

    def min_y(self) -> int:
        return min(self.coords[i][1] for i in range(4))

    def max_y(self) -> int:
        return max(self.coords[i][1] for i in range(4))

    def rotate_left(self) -> Shape:
        if self._piece_shape == Tetromino.SquareShape:
            return self
        result = Shape()
        result._piece_shape = self._piece_shape
        for i in range(4):
            result.set_x(i, self.y(i))
            result.set_y(i, -self.x(i))
        return result

    def rotate_right(self) -> Shape:
        if self._piece_shape == Tetromino.SquareShape:
            return self
        result = Shape()
        result._piece_shape = self._piece_shape
        for i in range(4):
            result.set_x(i, -self.y(i))
            result.set_y(i, self.x(i))
        return result


class TetrisBoard(QFrame):
    board_width = 10
    board_height = 22

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.timer = QBasicTimer()
        self.is_started = False
        self.is_paused = False
        self.is_waiting_after_line = False

        self.cur_piece = Shape()
        self.next_piece = Shape()
        self.cur_x = 0
        self.cur_y = 0

        self.num_lines_removed = 0
        self.num_pieces_dropped = 0
        self.score = 0
        self.level = 1
        self.board: list[Tetromino] = []

        self.setFrameStyle(QFrame.Shape.Panel | QFrame.Shadow.Sunken)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.clear_board()
        self.next_piece.set_random_shape()
        self.start()

    def sizeHint(self) -> QSize:
        return QSize(
            TetrisBoard.board_width * 15 + self.frameWidth() * 2,
            TetrisBoard.board_height * 15 + self.frameWidth() * 2,
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(
            TetrisBoard.board_width * 8 + self.frameWidth() * 2,
            TetrisBoard.board_height * 8 + self.frameWidth() * 2,
        )

    def start(self) -> None:
        if self.is_paused:
            return
        self.is_started = True
        self.is_waiting_after_line = False
        self.num_lines_removed = 0
        self.num_pieces_dropped = 0
        self.score = 0
        self.level = 1
        self.clear_board()
        self.new_piece()
        self.timer.start(self.timeout_time(), self)

    def pause(self) -> None:
        if not self.is_started:
            return

        self.is_paused = not self.is_paused
        if self.is_paused:
            self.timer.stop()
        else:
            self.timer.start(self.timeout_time(), self)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)

        painter = QPainter(self)
        rect = self.contentsRect()

        if self.is_paused:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Paused")
            return

        board_top = rect.bottom() - TetrisBoard.board_height * self.square_height()

        for i in range(TetrisBoard.board_height):
            for j in range(TetrisBoard.board_width):
                shape = self.shape_at(j, TetrisBoard.board_height - i - 1)
                if shape != Tetromino.NoShape:
                    self.draw_square(
                        painter,
                        int(rect.left() + j * self.square_width()),
                        int(board_top + i * self.square_height()),
                        shape,
                    )

        if self.cur_piece.shape() != Tetromino.NoShape:
            for i in range(4):
                x = self.cur_x + self.cur_piece.x(i)
                y = self.cur_y - self.cur_piece.y(i)
                self.draw_square(
                    painter,
                    int(rect.left() + x * self.square_width()),
                    int(board_top + (TetrisBoard.board_height - y - 1) * self.square_height()),
                    self.cur_piece.shape(),
                )

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self.is_started or self.is_paused or self.cur_piece.shape() == Tetromino.NoShape:
            super().keyPressEvent(event)
            return

        key = event.key()

        if key == Qt.Key.Key_P:
            self.pause()
            return

        if key == Qt.Key.Key_Left:
            self.try_move(self.cur_piece, self.cur_x - 1, self.cur_y)
        elif key == Qt.Key.Key_Right:
            self.try_move(self.cur_piece, self.cur_x + 1, self.cur_y)
        elif key == Qt.Key.Key_Down:
            self.try_move(self.cur_piece.rotate_right(), self.cur_x, self.cur_y)
        elif key == Qt.Key.Key_Up:
            self.try_move(self.cur_piece.rotate_left(), self.cur_x, self.cur_y)
        elif key == Qt.Key.Key_Space:
            self.drop_down()
        elif key == Qt.Key.Key_D:
            self.one_line_down()
        else:
            super().keyPressEvent(event)

    def timerEvent(self, event) -> None:  # noqa: N802
        if event.timerId() == self.timer.timerId():
            if self.is_waiting_after_line:
                self.is_waiting_after_line = False
                self.new_piece()
                self.timer.start(self.timeout_time(), self)
            else:
                self.one_line_down()
        else:
            super().timerEvent(event)

    def clear_board(self) -> None:
        self.board = [
            Tetromino.NoShape
            for _ in range(TetrisBoard.board_width * TetrisBoard.board_height)
        ]

    def shape_at(self, x: int, y: int) -> Tetromino:
        return self.board[(y * TetrisBoard.board_width) + x]

    def set_shape_at(self, x: int, y: int, shape: Tetromino) -> None:
        self.board[(y * TetrisBoard.board_width) + x] = shape

    def square_width(self) -> float:
        return self.contentsRect().width() / TetrisBoard.board_width

    def square_height(self) -> float:
        return self.contentsRect().height() / TetrisBoard.board_height

    def timeout_time(self) -> int:
        return int(1000 / (1 + self.level))

    def drop_down(self) -> None:
        drop_height = 0
        new_y = self.cur_y
        while new_y > 0:
            if not self.try_move(self.cur_piece, self.cur_x, new_y - 1):
                break
            new_y -= 1
            drop_height += 1
        self.piece_dropped(drop_height)

    def one_line_down(self) -> None:
        if not self.try_move(self.cur_piece, self.cur_x, self.cur_y - 1):
            self.piece_dropped(0)

    def piece_dropped(self, drop_height: int) -> None:
        for i in range(4):
            x = self.cur_x + self.cur_piece.x(i)
            y = self.cur_y - self.cur_piece.y(i)
            self.set_shape_at(x, y, self.cur_piece.shape())

        self.num_pieces_dropped += 1
        if self.num_pieces_dropped % 25 == 0:
            self.level += 1
            self.timer.start(self.timeout_time(), self)

        self.score += drop_height + 7
        self.remove_full_lines()

        if not self.is_waiting_after_line:
            self.new_piece()

    def remove_full_lines(self) -> None:
        full_lines = 0

        i = TetrisBoard.board_height - 1
        while i >= 0:
            line_is_full = True
            for j in range(TetrisBoard.board_width):
                if self.shape_at(j, i) == Tetromino.NoShape:
                    line_is_full = False
                    break

            if line_is_full:
                full_lines += 1
                for k in range(i, TetrisBoard.board_height - 1):
                    for j in range(TetrisBoard.board_width):
                        self.set_shape_at(j, k, self.shape_at(j, k + 1))

                for j in range(TetrisBoard.board_width):
                    self.set_shape_at(j, TetrisBoard.board_height - 1, Tetromino.NoShape)
            else:
                i -= 1

        if full_lines > 0:
            self.num_lines_removed += full_lines
            self.score += 10 * full_lines

            self.timer.start(500, self)
            self.is_waiting_after_line = True
            self.cur_piece.set_shape(Tetromino.NoShape)
            self.update()

    def new_piece(self) -> None:
        self.cur_piece = self.next_piece
        self.next_piece = Shape()
        self.next_piece.set_random_shape()

        self.cur_x = TetrisBoard.board_width // 2 + 1
        self.cur_y = TetrisBoard.board_height - 1 + self.cur_piece.min_y()

        if not self.try_move(self.cur_piece, self.cur_x, self.cur_y):
            self.cur_piece.set_shape(Tetromino.NoShape)
            self.timer.stop()
            self.is_started = False

    def try_move(self, new_piece: Shape, new_x: int, new_y: int) -> bool:
        for i in range(4):
            x = new_x + new_piece.x(i)
            y = new_y - new_piece.y(i)

            if x < 0 or x >= TetrisBoard.board_width or y < 0 or y >= TetrisBoard.board_height:
                return False
            if self.shape_at(x, y) != Tetromino.NoShape:
                return False

        self.cur_piece = new_piece
        self.cur_x = new_x
        self.cur_y = new_y
        self.update()
        return True

    def draw_square(self, painter: QPainter, x: int, y: int, shape: Tetromino) -> None:
        color_table = [
            0x000000,
            0xCC6666,
            0x66CC66,
            0x6666CC,
            0xCCCC66,
            0xCC66CC,
            0x66CCCC,
            0xDAAA00,
        ]

        color = QColor(color_table[int(shape)])
        square_w = int(self.square_width())
        square_h = int(self.square_height())

        painter.fillRect(x + 1, y + 1, square_w - 2, square_h - 2, color)

        painter.setPen(color.lighter())
        painter.drawLine(x, y + square_h - 1, x, y)
        painter.drawLine(x, y, x + square_w - 1, y)

        painter.setPen(color.darker())
        painter.drawLine(x + 1, y + square_h - 1, x + square_w - 1, y + square_h - 1)
        painter.drawLine(x + square_w - 1, y + square_h - 1, x + square_w - 1, y + 1)